/*
 * Click nbfs://nbhost/SystemFileSystem/Templates/Licenses/license-default.txt to change this license
 * Click nbfs://nbhost/SystemFileSystem/Templates/Classes/Class.java to edit this template
 */
package calculadoradistribuida;

/**
 *
 * @author Administrator
 */
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.Socket;
import javafx.event.ActionEvent;
import javafx.fxml.FXML;
import javafx.scene.control.Button;
import javafx.scene.control.TextField;

public class Controller {
    
    @FXML
    private TextField txt_resultado;
    private Socket clientSocket;
    private PrintWriter out;
    private BufferedReader in;
    
    String operador = "";
    long numero_uno; long numero_dos;
    
    public void Numero (ActionEvent ae){
        String numero = ((Button)ae.getSource()).getText();
        txt_resultado.setText(txt_resultado.getText()+numero);
    }

    public void Operacion (ActionEvent ae) throws IOException{
        String operacion = ((Button)ae.getSource()).getText();
        if(!operacion.equals("=")){
            if(!operador.equals("")){
                return;
            }
            operador = operacion;
            numero_uno = Long.parseLong(txt_resultado.getText());
            txt_resultado.setText("");
        } else {
            if(operador.equals("")){
                return;
            }
            numero_dos = Long.parseLong(txt_resultado.getText());
            calculadora(numero_uno, numero_dos, operador);
            operador="";
        }
    }
    
    public void calculadora(long n1, long n2, String op) throws IOException {
        clientSocket = new Socket("127.0.0.1", 6667);
        out = new PrintWriter(clientSocket.getOutputStream(), true);
        in = new BufferedReader(new InputStreamReader(clientSocket.getInputStream()));
        out.println(n1 + "," + n2 + "," + op);
        String resultado = in.readLine(); 
        txt_resultado.setText(resultado);

        clientSocket.close();
    }
    public void initialize() throws IOException {
        
    }
    
}