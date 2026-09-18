/*
 * Click nbfs://nbhost/SystemFileSystem/Templates/Licenses/license-default.txt to change this license
 * Click nbfs://nbhost/SystemFileSystem/Templates/Classes/Main.java to edit this template
 */
package calculadoradistribuida;

/**
 *
 * @author Administrator
 */
import javafx.application.Application;
import javafx.fxml.FXMLLoader;
import javafx.scene.Parent;
import javafx.scene.Scene;
import javafx.stage.Stage;

public class CalculadoraDistribuida extends Application {

    @Override
    public void start(Stage primaryStage) throws Exception{
        Parent root = FXMLLoader.load(getClass().getResource("calculadoradistribuida.fxml"));
        primaryStage.setTitle("Calculadora 1");
        primaryStage.setScene(new Scene(root));
        primaryStage.show();
        
        Parent root2 = FXMLLoader.load(getClass().getResource("calculadoradistribuida.fxml"));
        Stage stage2 = new Stage();
        stage2.setTitle("Calculadora 2");
        stage2.setScene(new Scene(root2));
        stage2.show();
        
        Parent root3 = FXMLLoader.load(getClass().getResource("calculadoradistribuida.fxml"));
        Stage stage3 = new Stage();
        stage3.setTitle("Calculadora 3");
        stage3.setScene(new Scene(root3));
        stage3.show();
    }


    public static void main(String[] args) {
        launch(args);
    }
}